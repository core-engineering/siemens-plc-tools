"""Primary and postfix: literals, variables, members, indexing, calls.

Every shape here is transcribed from the production corpus, not invented. The
statement parser's first release produced seven defects, all of them from shapes
written from memory.

`tokenize`, not `tokenize_with_newlines`: `Region.tokens` carries no NEWLINE in
production, and injecting them here would test something the parser never sees.
"""

from plc_code.parser.expression_parser import parse_expression
from plc_code.parser.expressions import FunctionCall, Index, Literal, Member, VariableRef
from plc_code.parser.lexer import TokenType, tokenize


def _parse(source: str):
    return parse_expression([t for t in tokenize(source) if t.type is not TokenType.EOF])


class TestLiterals:
    def test_a_number(self) -> None:
        result = _parse("42")
        assert result.errors == []
        assert isinstance(result.expression, Literal)
        assert result.expression.value == "42"

    def test_a_real(self) -> None:
        assert isinstance(_parse("1.5").expression, Literal)

    def test_true_and_false(self) -> None:
        for text in ("TRUE", "FALSE", "true"):
            node = _parse(text).expression
            assert isinstance(node, Literal), text


class TestVariableRef:
    def test_a_local_variable(self) -> None:
        node = _parse("#armNumber").expression
        assert isinstance(node, VariableRef)
        assert node.name == "armNumber"
        assert node.is_local is True

    def test_a_quoted_block(self) -> None:
        node = _parse('"QuayData"').expression
        assert isinstance(node, VariableRef)
        assert node.name == "QuayData"
        assert node.is_local is False


class TestPostfix:
    def test_a_member_chain(self) -> None:
        """`#armSetpoint.profile.status` — 11,057 member accesses in the corpus."""
        node = _parse("#armSetpoint.profile.status").expression
        assert isinstance(node, Member)
        assert node.name == "status"
        assert isinstance(node.base, Member)
        assert node.base.name == "profile"

    def test_indexing(self) -> None:
        node = _parse("#arms[#i]").expression
        assert isinstance(node, Index)
        assert isinstance(node.index, VariableRef)

    def test_the_production_shape(self) -> None:
        """`"Data".arms[#armNumber].status.ersState`, transcribed from the corpus."""
        node = _parse('"QuayData".arms[#armNumber].status.ersState').expression
        assert isinstance(node, Member)
        assert node.name == "ersState"

    def test_an_index_expression_may_be_arithmetic(self) -> None:
        node = _parse("#arms[#i]").expression
        assert isinstance(node, Index)


class TestFunctionCall:
    def test_a_single_argument(self) -> None:
        node = _parse("ABS(#x)").expression
        assert isinstance(node, FunctionCall)
        assert node.name == "ABS"
        assert len(node.arguments) == 1

    def test_a_conversion(self) -> None:
        node = _parse('INT_TO_USINT("Iface".status.state)').expression
        assert isinstance(node, FunctionCall)
        assert node.name == "INT_TO_USINT"

    def test_no_arguments(self) -> None:
        node = _parse("RD_SYS_T()").expression
        assert isinstance(node, FunctionCall)
        assert node.arguments == []


class TestGrouping:
    def test_parentheses_do_not_appear_in_the_tree(self) -> None:
        """Grouping is a reading rule, not a node."""
        node = _parse("(#a)").expression
        assert isinstance(node, VariableRef)


class TestErrors:
    def test_an_unreadable_token_is_reported_not_guessed(self) -> None:
        result = _parse("@")
        assert result.expression is None
        assert len(result.errors) == 1
        assert result.errors[0].line == 1
