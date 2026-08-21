"""Recursive-descent expression parser over an SCL token stream.

Like the statement parser, it reads tokens rather than text: ``Region.content``
is a lossy re-serialisation and the tokens are the only place adjacency (and
therefore `>=` versus `> =`) is decidable. The parser never guesses — a
construct it cannot read produces a ``ParseError`` and the expression is
reported as unreadable rather than reconstructed from a partial match.

The primary and postfix layer reads literals, variable references (`#local`,
`"Global"`), member access, indexing, function calls, and parenthesised
grouping. Above it sits the operator-precedence chain: a left-associative
level per precedence tier (`OR`, `AND`, comparisons, `+`/`-`, `*`/`/`/`MOD`),
then right-associative `**`, then unary `NOT`/`-`. ``_parse_expression`` is
the seam both layers share — every sub-expression (index, call argument,
grouping) re-enters through it, so the chain applies everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from plc_code.parser.expressions import (
    BinaryOp,
    CallArgument,
    Expression,
    FunctionCall,
    Grouping,
    Index,
    Literal,
    Member,
    TypedLiteral,
    UnaryOp,
    VariableRef,
)
from plc_code.parser.lexer import KEYWORDS, Token, TokenType
from plc_code.parser.statements import ParseError
from plc_code.parser.token_stream import TokenStream, adjacent, composite_operator

#: Identifier spellings that read as a boolean literal rather than a name.
_NAME_TOKEN_TYPES = frozenset({TokenType.IDENTIFIER, *KEYWORDS.values()})
"""Token types that may stand for a name in an expression.

The lexer's 25 keywords are all block and declaration structure —
``FUNCTION_BLOCK``, ``VAR_INPUT``, ``STRUCT``, ``REGION`` — so none of them can
legitimately appear inside a REGION body, and one that does is a name the
programmer chose: `#function`, `.type`. Together those cost 76 of the corpus's
expression errors. This is fixed here rather than in the lexer on purpose: the
lexer also feeds ``Region.content``, which 27 rules and the transpiler read byte
for byte.
"""


_BOOLEAN_LITERALS = {"TRUE", "FALSE"}

_IMPLICIT_VARIABLES = {"ENO"}
"""Bare identifiers SCL defines itself, which are variables despite having no
`#` or quotes.

`ENO` is the implicit enable output every block carries; the corpus assigns it
directly (`ENO := TRUE;`). The set is deliberately this small: the
bare-identifier error is what catches every construct the grammar cannot read,
so widening it past the names SCL actually defines would empty the grammar of
its ability to refuse.
"""

#: Single-character operator tokens, mapped to their SCL spelling. Distinct
#: from ``token_stream._OPERATOR_TYPES``: that module owns the adjacent
#: composite table (``>=``, ``<=`` ...), this is only the fallback for a
#: lone operator character, read here rather than exported because it is
#: needed nowhere else.
_SIMPLE_OPERATOR_TYPES: dict[TokenType, str] = {
    TokenType.PLUS: "+",
    TokenType.MINUS: "-",
    TokenType.STAR: "*",
    TokenType.SLASH: "/",
    TokenType.EQ: "=",
    TokenType.LT: "<",
    TokenType.GT: ">",
}


@dataclass
class ExpressionResult:
    """What a token slice parsed into, and what it could not.

    Attributes
    ----------
    expression : Expression | None
        The parsed expression, or ``None`` when the slice was not read as one
        in full — either because a construct in it was unreadable, or
        because the parse completed on a leading part of the slice and
        tokens remained after it. Both cases record a ``ParseError`` in
        ``errors``; a partial tree is never returned in its place, so
        ``expression is not None`` alone is safe for a caller to trust
        without also checking ``consumed``.
    errors : list[ParseError]
        One entry per construct the parser could not read, in the order the
        parser encountered them, plus a final entry when the slice was not
        fully consumed despite an otherwise clean parse. Default is an empty
        list.
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

    #: Left-associative levels, weakest to strongest. Each entry lists that
    #: level's operators; the chain is walked by _binary_level.
    _LEVELS: tuple[frozenset[str], ...] = (
        frozenset({"OR"}),
        frozenset({"AND", "&"}),
        frozenset({"=", "<>", "<", ">", "<=", ">="}),
        frozenset({"+", "-"}),
        frozenset({"*", "/", "MOD"}),
    )

    def _parse_expression(self) -> Expression | None:
        """Top-level expression entry point: the operator-precedence chain.

        Returns
        -------
        Expression | None
            The parsed expression, or ``None`` when the cursor was on a
            construct this parser cannot read (an error was recorded).
        """
        return self._binary_level(0)

    def _binary_level(self, level: int, seed: Expression | None = None) -> Expression | None:
        """One left-associative binary level.

        Parameters
        ----------
        level : int
            Index into ``_LEVELS``. Past the last one, descend to
            ``_parse_power``.

        Returns
        -------
        Expression | None
            The level's tree, or None when the left operand could not be
            read, or when an operator was consumed but its right operand
            could not: a binary node built from a missing operand would be a
            partial tree presented as a complete one, which the caller has
            no way to tell apart from a real parse (the same rule
            ``_parse_postfix`` and ``_parse_function_call`` already follow).
            ``_peek_operator_in`` can itself record an error without
            consuming anything (the ``XOR`` case) — that counts too, so a
            failed lookup only returns ``left`` when no new error appeared.
        """
        if level >= len(self._LEVELS):
            return self._parse_power(seed)
        left = self._binary_level(level + 1, seed)
        if left is None:
            return None
        while True:
            error_count = len(self._errors)
            operator = self._peek_operator_in(self._LEVELS[level])
            if operator is None:
                folded = self._split_folded_minus(self._LEVELS[level])
                if folded is not None:
                    right = self._binary_level(level + 1, seed=folded)
                    if right is None:
                        return None
                    left = BinaryOp(
                        line=folded.line,
                        column=folded.column - 1,
                        operator="-",
                        left=left,
                        right=right,
                    )
                    continue
                return None if len(self._errors) > error_count else left
            token = self._stream.peek()
            self._consume_operator(operator)
            right = self._binary_level(level + 1)
            if right is None:
                return None
            left = BinaryOp(
                line=token.line,
                column=token.column,
                operator=operator,
                left=left,
                right=right,
            )

    def _split_folded_minus(self, names: frozenset[str]) -> Literal | None:
        """Split a `NUMBER` the lexer folded a leading `-` into.

        The lexer turns `-` followed by a digit into one `NUMBER` token
        whatever precedes it, spacing included: `#a-1` and `#a -1` both come
        out as ``IDENTIFIER:'a' NUMBER:'-1'``. It cannot do better, because the
        two readings are told apart by whether an operand precedes —
        ``f(#a, -1)`` passes a negative literal, ``f(#a -1)`` passes a
        subtraction — and that is the parser's knowledge, not the lexer's.

        Called only when the operator lookup failed inside ``_binary_level``'s
        loop, which by construction runs after a left operand has been read.
        Everywhere else a folded token reaches ``_parse_primary`` and stays the
        negative literal it is. Fixing it here rather than in the lexer also
        leaves ``Region.content`` untouched, which 27 rules and the transpiler
        read byte for byte.

        Parameters
        ----------
        names : frozenset[str]
            The precedence level's operator set. The split applies at the
            additive level only; every other level must leave the token alone
            so precedence still binds the subtraction where it belongs.

        Returns
        -------
        Literal | None
            The number without its sign, positioned one column right of the
            `-`; None when the cursor is not on a folded token or the level is
            not the additive one. Nothing is consumed in that case.
        """
        if "-" not in names:
            return None
        token = self._stream.peek()
        if token.type is not TokenType.NUMBER or not token.value.startswith("-"):
            return None
        self._stream.advance()
        return Literal(line=token.line, column=token.column + 1, value=token.value[1:])

    def _parse_power(self, seed: Expression | None = None) -> Expression | None:
        """``**``, the only RIGHT-associative operator.

        ``2 ** 3 ** 2`` is ``2 ** (3 ** 2)`` = 512, not 64. Hence recursing
        into itself on the right rather than looping.

        Parameters
        ----------
        seed : Expression | None
            An operand already read, used in place of reading one here. Only
            ``_split_folded_minus`` supplies it: the number it recovered has to
            enter the chain at the bottom so `#a-1*2` binds `1*2`, exactly as
            the spaced `#a - 1 * 2` does.

        Returns
        -------
        Expression | None
            The parsed expression; ``None`` on the same terms as
            ``_binary_level`` (missing left operand, missing right operand
            after a consumed ``**``, or an error surfaced by
            ``_peek_operator_in`` itself).
        """
        left = self._parse_unary() if seed is None else seed
        if left is None:
            return None
        error_count = len(self._errors)
        if self._peek_operator_in(frozenset({"**"})) is None:
            return None if len(self._errors) > error_count else left
        token = self._stream.peek()
        self._consume_operator("**")
        right = self._parse_power()
        if right is None:
            return None
        return BinaryOp(line=token.line, column=token.column, operator="**", left=left, right=right)

    def _parse_unary(self) -> Expression | None:
        """``NOT x`` and ``-x``.

        Unary sits ABOVE ``**`` in the chain, so ``-2 ** 2`` gives
        ``-(2 ** 2)``: the operand of a leading ``-`` or ``NOT`` is read
        with ``_parse_power``, not by recursing back into ``_parse_unary``
        directly, so that a ``**`` following the operand is bound before the
        unary operator wraps it. ``_parse_power`` calls back into
        ``_parse_unary`` for its own left side, so a run of unary operators
        (``NOT NOT #a``) still nests correctly through that mutual
        recursion; only the base case, no unary token at the cursor, reads
        straight through ``_parse_postfix``.

        Returns
        -------
        Expression | None
            The parsed expression; ``None`` when a ``-`` or ``NOT`` was
            consumed but no operand followed, or when ``_parse_postfix``
            found nothing readable (an error was recorded either way).
        """
        token = self._stream.peek()
        if token.type is TokenType.MINUS:
            self._stream.advance()
            operand = self._parse_power()
            if operand is None:
                return None
            return UnaryOp(line=token.line, column=token.column, operator="-", operand=operand)
        if token.type is TokenType.IDENTIFIER and token.value.upper() == "NOT":
            self._stream.advance()
            operand = self._parse_power()
            if operand is None:
                return None
            return UnaryOp(line=token.line, column=token.column, operator="NOT", operand=operand)
        return self._parse_postfix()

    def _peek_operator_in(self, names: frozenset[str]) -> str | None:
        """The SCL form of the operator at the cursor, if it is one of ``names``.

        Checked in order: a composite pair (``>=``, ``**`` ...) via
        ``composite_operator`` — the single owner of that table — then a
        word operator (``AND``, ``OR``, ``MOD``) read off an ``IDENTIFIER``
        token, then a lone operator character. ``XOR`` is recognised here
        unconditionally, regardless of ``names``: it is never a member of
        any precedence level, so without this check it would silently stop
        the chain instead of being reported — the corpus has zero
        occurrences, and guessing at its translation would be worse than
        refusing it.

        Parameters
        ----------
        names : frozenset[str]
            The operator spellings this call accepts.

        Returns
        -------
        str | None
            The operator's SCL spelling when it is a member of ``names``,
            otherwise None. Nothing is consumed either way.
        """
        first = self._stream.peek()
        second = self._stream.peek(1)
        composed = composite_operator(first, second)
        if composed is not None and composed in names:
            return composed

        if first.type is TokenType.IDENTIFIER:
            word = first.value.upper()
            if word == "XOR":
                self._error(first, "an operator this toolchain translates")
                return None
            if word in names:
                return word
            return None

        # `&` is SCL's other spelling of AND. The lexer has no token for it, so
        # it arrives as UNKNOWN and is recognised by its value — never by the
        # type, which is the lexer's catch-all. The spelling is returned as
        # itself rather than folded into "AND": both are real source, and a
        # consumer that cannot tell them apart cannot render either one back.
        if first.type is TokenType.UNKNOWN and first.value == "&" and "&" in names:
            return "&"

        simple = _SIMPLE_OPERATOR_TYPES.get(first.type)
        if simple is not None and simple in names:
            return simple
        return None

    def _consume_operator(self, operator: str) -> None:
        """Advance the cursor past ``operator``.

        Parameters
        ----------
        operator : str
            The operator returned by a prior, unconsumed call to
            ``_peek_operator_in``. A word operator (``AND``, ``OR``,
            ``MOD``) and a lone character both occupy one token; a
            composite (``>=``, ``**`` ...) occupies two adjacent ones.
        """
        self._stream.advance()
        if len(operator) == 2 and not operator.isalpha():
            self._stream.advance()

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
                # A member may carry its own `#`: `#armSetpoint.#angularSpeeds`.
                # Rejecting it cost 234 of the corpus's expression errors. The
                # flag is kept because `.name` and `.#name` are different source.
                is_local = False
                if self._stream.peek().type is TokenType.HASH:
                    self._stream.advance()
                    is_local = True
                # SCL reads a bit, byte or word of the base directly:
                # `"QuayData".rcu.input.statusByte.%X0`. The lexer has no token
                # for `%`, so the selector arrives as UNKNOWN('%') followed by an
                # ordinary name, and only adjacency separates that from a stray
                # character — the same rule the binary operators use.
                is_absolute = False
                percent = self._stream.peek()
                if percent.type is TokenType.UNKNOWN and percent.value == "%":
                    if not adjacent(percent, self._stream.peek(1)):
                        self._error(self._stream.peek(1), "a selector attached to '%'")
                        return None
                    self._stream.advance()
                    is_absolute = True
                name_token = self._stream.peek()
                # A numeric member is a bit index written without the `%`:
                # `#word.0`, and the `.0` tail of `"Data".%DBX0.0`. A quoted one
                # is TIA Portal's other way of writing a name the lexer reserves
                # — `."type"`, 80 times in the corpus, alongside the bare `.type`
                # that `_NAME_TOKEN_TYPES` already covers.
                is_quoted_member = name_token.type is TokenType.STRING
                if (
                    name_token.type not in _NAME_TOKEN_TYPES
                    and name_token.type is not TokenType.NUMBER
                    and not is_quoted_member
                ):
                    self._error(name_token, "a member name after '.'")
                    return None
                self._stream.advance()
                node = Member(
                    line=token.line,
                    column=token.column,
                    base=node,
                    name=name_token.value[1:-1] if is_quoted_member else name_token.value,
                    is_local=is_local,
                    is_absolute=is_absolute,
                    is_quoted=is_quoted_member,
                )
                continue

            if token.type is TokenType.LBRACKET:
                self._stream.advance()
                # A multi-dimensional array is indexed in one pair of brackets:
                # `#matrixResult[#rows, #columns]`. Reading only the first
                # subscript left the comma trailing, and cost 12 of the corpus's
                # expression errors.
                indices: list[Expression] = []
                while True:
                    index = self._parse_expression()
                    if index is None:
                        return None
                    indices.append(index)
                    if self._stream.match(TokenType.COMMA):
                        self._stream.advance()
                        continue
                    break
                if not self._expect(TokenType.RBRACKET, "']'"):
                    return None
                node = Index(line=token.line, column=token.column, base=node, indices=indices)
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

        # The value is the longest run of adjacent NUMBER/IDENTIFIER tokens:
        # `5` `s` -> "5s", `1` `h` `30` `m` -> "1h30m". Adjacency alone is not
        # enough to stop the run: real SCL puts no space before a closing
        # delimiter either, so `ABS(T#5s)`'s `)` and `T#5s+1`'s `+` are both
        # adjacent to the last value token and must be excluded by type.
        # SCL also chains the prefixes: `b#16#FF` is byte, hexadecimal, FF. The
        # run therefore crosses a `#` too — but only one that is adjacent on
        # both sides, so a spaced `#` still belongs to the operand after it and
        # `16#FF + #a` stays readable.
        parts: list[str] = []
        previous = hash_token
        while not self._stream.at_end():
            token = self._stream.peek()
            if not adjacent(previous, token):
                break
            if token.type in (TokenType.NUMBER, TokenType.IDENTIFIER):
                pass
            elif token.type is TokenType.HASH and self._continues_typed_literal(token):
                pass
            else:
                break
            self._stream.advance()
            parts.append(token.value)
            previous = token

        return TypedLiteral(
            line=prefix.line,
            column=prefix.column,
            prefix=prefix.value,
            value="".join(parts),
        )

    def _continues_typed_literal(self, hash_token: Token) -> bool:
        """Whether a `#` inside a typed literal's value has a value behind it.

        Parameters
        ----------
        hash_token : Token
            The `#` at the cursor, already known to be adjacent to what precedes
            it.

        Returns
        -------
        bool
            True when an adjacent ``NUMBER`` or ``IDENTIFIER`` follows, which is
            what makes `b#16#FF` one literal. False for a `#` with nothing
            usable behind it, so it is left for the caller rather than swallowed.
        """
        following = self._stream.peek(1)
        return adjacent(hash_token, following) and following.type in (
            TokenType.NUMBER,
            TokenType.IDENTIFIER,
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
            if token.value.upper() in _IMPLICIT_VARIABLES:
                self._stream.advance()
                return VariableRef(line=token.line, column=token.column, name=token.value, is_local=False)
            self._error(token, "an expression")
            return None

        if token.type is TokenType.HASH:
            return self._parse_local_variable()

        if token.type is TokenType.UNKNOWN and token.value == "%":
            return self._parse_absolute_address()

        if token.type is TokenType.STRING:
            # A quoted name followed by `(` is a call on a user block, not a
            # variable: `"ConvertAngleSafetyProcess"(...)`. Reading it as a
            # variable left the `(` trailing and cost 235 of the corpus's
            # expression errors. Unlike a typed literal, this does not depend on
            # adjacency — `"Name" (x)` is the same call.
            if self._stream.peek(1).type is TokenType.LPAREN:
                return self._parse_function_call()
            self._stream.advance()
            return VariableRef(line=token.line, column=token.column, name=token.value[1:-1], is_local=False)

        if token.type is TokenType.LPAREN:
            return self._parse_grouping()

        self._error(token, "an expression")
        return None

    def _parse_absolute_address(self) -> Expression | None:
        """Parse `%name`, the cursor already on the `%`.

        SCL addresses memory directly — `%DB150.%DBX31.1`, `%I0.0`, `%M10.2` —
        and the corpus writes 211 of them. The `%` has no token of its own, so
        adjacency is what separates an address from a stray character, the same
        rule the binary operators use.

        Returns
        -------
        Expression | None
            A ``VariableRef`` with ``is_absolute=True``; ``None`` when `%` is
            not immediately followed by a name (an error was recorded). Any
            `.member` or `[index]` after it is folded in by ``_parse_postfix``,
            as for any other primary.
        """
        percent = self._stream.advance()  # '%'
        name_token = self._stream.peek()
        if not adjacent(percent, name_token) or name_token.type not in _NAME_TOKEN_TYPES:
            self._error(name_token, "a name attached to '%'")
            return None
        self._stream.advance()
        return VariableRef(
            line=percent.line,
            column=percent.column,
            name=name_token.value,
            is_local=False,
            is_absolute=True,
        )

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
        if name_token.type not in _NAME_TOKEN_TYPES:
            self._error(name_token, "an identifier after '#'")
            return None
        self._stream.advance()
        return VariableRef(
            line=hash_token.line, column=hash_token.column, name=name_token.value, is_local=True
        )

    def _parse_function_call(self) -> Expression | None:
        """Parse `name(args)`, the cursor already on the name.

        The name is a bare identifier for a builtin (`ABS(#x)`) or a quoted
        block name for a user block (`"Scaling"(#x)`). Only reached once the
        caller has confirmed an `(` follows it.

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
        name_token = self._stream.advance()  # IDENTIFIER or STRING
        self._stream.advance()  # LPAREN
        # A quoted callee names a user block; a bare one is a builtin such as
        # ABS. The quotes are stripped from the name and the distinction kept in
        # the flag, matching how VariableRef stores a quoted name.
        is_quoted = name_token.type is TokenType.STRING
        name = name_token.value[1:-1] if is_quoted else name_token.value

        arguments: list[CallArgument] = []
        if not self._stream.match(TokenType.RPAREN):
            while True:
                argument = self._parse_argument()
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
            line=name_token.line,
            column=name_token.column,
            name=name,
            arguments=arguments,
            is_quoted=is_quoted,
        )

    def _parse_argument(self) -> CallArgument | None:
        """Parse one call argument, named (`IN := #x`, `OUT => #y`) or positional.

        A parameter name is a bare identifier, which is not an expression on its
        own, so the binding has to be recognised before the value is read: the
        corpus writes named arguments far more often than positional ones, and
        without this the argument fails at its own name.

        Returns
        -------
        CallArgument | None
            The argument; ``None`` when its value could not be read (an error
            was recorded). ``name`` is empty and ``is_output`` false for a
            positional argument.
        """
        name = ""
        is_output = False
        is_quoted_name = False
        # The name may be quoted: TIA Portal writes `"Atan2"("x" := #A, y := #B)`,
        # quoting one parameter and leaving its neighbour bare in the same call.
        # Without the `:=` or `=>` behind it a quoted token is an ordinary global
        # read, so the lookahead decides, not the token type alone.
        head = self._stream.peek()
        if head.type in (TokenType.IDENTIFIER, TokenType.STRING):
            follower = self._stream.peek(1)
            arrow = composite_operator(follower, self._stream.peek(2)) == "=>"
            if follower.type is TokenType.ASSIGN or arrow:
                is_quoted_name = head.type is TokenType.STRING
                name = head.value[1:-1] if is_quoted_name else head.value
                self._stream.advance()
                self._stream.advance()
                if arrow:
                    self._stream.advance()
                    is_output = True

        value = self._parse_expression()
        if value is None:
            return None
        return CallArgument(value=value, name=name, is_output=is_output, is_quoted_name=is_quoted_name)

    def _parse_grouping(self) -> Expression | None:
        """Parse `(expression)`, the cursor already on the `(`.

        The parentheses are source, not just a binding hint for an outer
        operator layer, so they are kept as a ``Grouping`` node around the
        inner expression rather than discarded.

        Returns
        -------
        Expression | None
            A ``Grouping`` wrapping the inner expression; ``None`` when
            nothing readable followed the `(`, or when the closing `)` is
            missing (an error was recorded either way).
        """
        paren = self._stream.advance()  # LPAREN
        inner = self._parse_expression()
        if inner is None:
            return None
        if not self._expect(TokenType.RPAREN, "')'"):
            return None
        return Grouping(line=paren.line, column=paren.column, inner=inner)

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

    A construct the parser cannot read at all is the obvious failure and was
    always reported. The other failure this also guards against is quieter:
    the parser can reach a valid expression and simply stop, leaving tokens
    unread after it (`` #a #b`` reads as `` #a`` and stops; ``B#16#01`` reads
    as the typed literal ``B#16`` and stops before the trailing ``#01``). Left
    unchecked, that reads as a clean parse — no error, a real tree — and a
    caller trusting ``.expression`` alone would silently act on a wrong
    result built from a prefix of its input. This function checks the
    stream's final position itself, so that case is turned into the same
    outcome as an unreadable construct: an error and ``expression is None``.

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
        The parsed expression, or ``None`` when the slice could not be read
        as one in full; any errors encountered (see above); and how many
        tokens of the slice were consumed. ``consumed`` is unaffected by this
        check — it still reports the cursor's own final position, not
        ``len(tokens)`` — so ``verify_expression_consumed`` keeps working
        exactly as before.
    """
    stream = TokenStream(tokens)
    parser = _ExpressionParser(stream)
    expression = parser.parse()
    errors = parser.errors
    consumed = stream.position()
    if expression is not None and consumed < len(tokens):
        trailing = tokens[consumed]
        errors = [
            *errors,
            ParseError(
                line=trailing.line,
                column=trailing.column,
                token_value=trailing.value,
                expected="the end of the expression (trailing tokens after a complete parse)",
            ),
        ]
        expression = None
    return ExpressionResult(expression=expression, errors=errors, consumed=consumed)


def verify_expression_consumed(tokens: list[Token], result: ExpressionResult) -> bool:
    """Whether the expression was read in full.

    Parameters
    ----------
    tokens : list[Token]
        The slice handed to ``parse_expression``.
    result : ExpressionResult
        What it returned.

    Returns
    -------
    bool
        True when every token was consumed by the tree or by an error. False
        signals truncation — the failure mode this invariant exists to make
        impossible.
    """
    return result.consumed == len(tokens)
