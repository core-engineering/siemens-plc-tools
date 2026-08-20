"""Two shapes SCL writes that the grammar had no branch for.

Both were invisible until `Network.tokens` exposed the SCL that sits outside
any REGION, which is where the corpus writes them:

    IF "ESD".ESD1[#b] & "PMS".mla_valid[#b] AND (...) THEN
    "DB_Stahl_Display".Arm_Sensors_Failure[1] := %DB150.%DBX31.1;

`&` is SCL's other spelling of `AND`, and `%` introduces an absolute address.
Neither has a token of its own: the lexer emits both as `UNKNOWN`, so each is
recognised by its value and by adjacency, never by token type alone.

`tokenize`, never `tokenize_with_newlines`: production token slices carry no
NEWLINE.
"""

from __future__ import annotations

from plc_code.parser.expression_parser import parse_expression, verify_expression_consumed
from plc_code.parser.expressions import BinaryOp, Index, Member, VariableRef
from plc_code.parser.lexer import TokenType, tokenize


def _tokens(source: str):
    return [t for t in tokenize(source) if t.type is not TokenType.EOF]


def _parse(source: str):
    return parse_expression(_tokens(source))


class TestAmpersandAsAnd:
    def test_an_ampersand_joins_two_operands(self) -> None:
        result = _parse("#a & #b")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.left == VariableRef(line=1, column=1, name="a", is_local=True)
        assert node.right == VariableRef(line=1, column=6, name="b", is_local=True)

    def test_the_spelling_is_kept_rather_than_normalised(self) -> None:
        # `&` and `AND` are the same operator and different source. Rewriting
        # one into the other would leave a consumer unable to render back what
        # was written, which is the rule every other spelling flag follows.
        assert _parse("#a & #b").expression.operator == "&"
        assert _parse("#a AND #b").expression.operator == "AND"

    def test_it_binds_like_and(self) -> None:
        # `OR` is looser, so the `&` group is the right operand of the `OR`.
        result = _parse("#a OR #b & #c")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "OR"
        assert isinstance(node.right, BinaryOp)
        assert node.right.operator == "&"

    def test_it_mixes_with_the_word_form_in_one_expression(self) -> None:
        result = _parse('"ESD".ESD1[#b] & "PMS".mla_valid[#b] AND #ok')
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "AND"
        assert isinstance(node.left, BinaryOp)
        assert node.left.operator == "&"

    def test_a_doubled_ampersand_is_an_error(self) -> None:
        result = _parse("#a && #b")
        assert result.errors != []
        assert result.expression is None

    def test_an_ampersand_with_no_right_operand_is_an_error(self) -> None:
        result = _parse("#a &")
        assert result.errors != []
        assert result.expression is None


class TestAbsoluteAddress:
    def test_an_absolute_address_is_a_variable(self) -> None:
        result = _parse("%DB150")
        assert result.errors == []
        assert result.expression == VariableRef(
            line=1, column=1, name="DB150", is_local=False, is_absolute=True
        )

    def test_a_plain_variable_is_not_marked_absolute(self) -> None:
        result = _parse("#a")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, VariableRef)
        assert node.is_absolute is False

    def test_the_whole_addressed_chain_is_read(self) -> None:
        result = _parse("%DB150.%DBX31.1")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "1"
        assert isinstance(node.base, Member)
        assert node.base.name == "DBX31"
        assert node.base.is_absolute is True
        assert node.base.base == VariableRef(
            line=1, column=1, name="DB150", is_local=False, is_absolute=True
        )

    def test_a_direct_input_address_is_read(self) -> None:
        result = _parse("%I0.0")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "0"
        assert isinstance(node.base, VariableRef)
        assert node.base.name == "I0"
        assert node.base.is_absolute is True

    def test_an_absolute_address_works_inside_an_expression(self) -> None:
        result = _parse("#ok AND %DB150.%DBX31.1")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "AND"
        assert isinstance(node.right, Member)

    def test_an_absolute_address_indexes_like_any_variable(self) -> None:
        result = _parse("%DB150.arr[#i]")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Index)
        assert isinstance(node.base, Member)

    def test_a_detached_percent_is_an_error(self) -> None:
        result = _parse("% DB150")
        assert result.errors != []
        assert result.expression is None

    def test_a_percent_with_no_name_is_an_error(self) -> None:
        result = _parse("%")
        assert result.errors != []
        assert result.expression is None


class TestConsumption:
    def test_both_shapes_consume_all_their_tokens(self) -> None:
        for source in ("#a & #b", "%DB150.%DBX31.1", "%I0.0"):
            tokens = _tokens(source)
            result = parse_expression(tokens)
            assert verify_expression_consumed(tokens, result) is True, source
