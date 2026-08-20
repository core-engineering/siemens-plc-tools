"""Two constructs the corpus uses that the grammar did not read.

Together they accounted for 469 of the 594 expression errors measured across
five production projects — 235 and 234 — and both are ordinary SCL rather than
anything exotic:

    "ConvertAngleSafetyProcess"("Iface".arm1.status.slewingAngle)
    #armSetpoint.#angularSpeeds["SLEWING"]

The first is a call whose callee is a quoted block name; the parser read the
quoted name as a variable and then choked on the `(`. The second is a member
access whose member carries a `#`; the parser expected a bare identifier after
the dot.

Both shapes are transcribed from the corpus, not invented. `tokenize`, never
`tokenize_with_newlines`: production `Region.tokens` carries no NEWLINE.
"""

from __future__ import annotations

from plc_code.parser.expression_parser import parse_expression, verify_expression_consumed
from plc_code.parser.expressions import FunctionCall, Index, Member, VariableRef
from plc_code.parser.lexer import TokenType, tokenize


def _tokens(source: str):
    return [t for t in tokenize(source) if t.type is not TokenType.EOF]


def _parse(source: str):
    return parse_expression(_tokens(source))


class TestQuotedNameCall:
    def test_a_quoted_callee_is_a_function_call(self) -> None:
        result = _parse('"ConvertAngleSafetyProcess"(#x)')
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert call.name == "ConvertAngleSafetyProcess"
        assert len(call.arguments) == 1

    def test_the_quotes_are_recorded_not_guessed(self) -> None:
        """The generator has to tell a user block from a builtin."""
        quoted = _parse('"Scaling"(#x)').expression
        bare = _parse("ABS(#x)").expression
        assert isinstance(quoted, FunctionCall) and quoted.is_quoted is True
        assert isinstance(bare, FunctionCall) and bare.is_quoted is False

    def test_the_production_shape(self) -> None:
        source = '"ConvertAngleSafetyProcess"("Iface".arm1.status.slewingAngle)'
        result = _parse(source)
        assert result.errors == []
        assert verify_expression_consumed(_tokens(source), result) is True

    def test_no_arguments(self) -> None:
        call = _parse('"Now"()').expression
        assert isinstance(call, FunctionCall)
        assert call.arguments == []

    def test_several_arguments(self) -> None:
        call = _parse('"Scale"(#raw, #min, #max)').expression
        assert isinstance(call, FunctionCall)
        assert len(call.arguments) == 3

    def test_a_quoted_name_without_a_paren_is_still_a_variable(self) -> None:
        """The negative case: `"QuayData".arms` must not become a call."""
        node = _parse('"QuayData"').expression
        assert isinstance(node, VariableRef)
        assert node.is_local is False
        assert node.name == "QuayData"

    def test_a_quoted_name_followed_by_a_member_is_still_a_variable(self) -> None:
        node = _parse('"QuayData".arms').expression
        assert isinstance(node, Member)
        assert isinstance(node.base, VariableRef)

    def test_a_space_before_the_paren_still_calls(self) -> None:
        """Unlike typed literals, a call does not depend on adjacency."""
        call = _parse('"Scaling" (#x)').expression
        assert isinstance(call, FunctionCall)


class TestHashPrefixedMember:
    def test_a_hash_prefixed_member_is_read(self) -> None:
        result = _parse("#armSetpoint.#angularSpeeds")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "angularSpeeds"

    def test_the_hash_is_recorded_not_dropped(self) -> None:
        """`.name` and `.#name` are different source; the tree says which."""
        hashed = _parse("#a.#b").expression
        plain = _parse("#a.b").expression
        assert isinstance(hashed, Member) and hashed.is_local is True
        assert isinstance(plain, Member) and plain.is_local is False

    def test_the_production_shape_with_an_index(self) -> None:
        source = '#armSetpoint.#angularSpeeds["SLEWING"]'
        result = _parse(source)
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Index)
        assert isinstance(node.base, Member)
        assert node.base.name == "angularSpeeds"
        assert verify_expression_consumed(_tokens(source), result) is True

    def test_chained_after_a_hash_member(self) -> None:
        node = _parse("#a.#b.c").expression
        assert isinstance(node, Member)
        assert node.name == "c"
        assert isinstance(node.base, Member)
        assert node.base.is_local is True

    def test_a_dot_hash_with_no_name_is_still_an_error(self) -> None:
        """Accepting `#` must not make a dangling one legal."""
        result = _parse("#a.#")
        assert result.errors != []
        assert result.expression is None
