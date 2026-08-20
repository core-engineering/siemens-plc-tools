"""The four expression shapes the grammar still refused after named arguments.

Each is ordinary SCL, transcribed from five production projects, and none is an
implementation bug — they are constructs the grammar simply did not cover:

    AND #function = "RCU_FUNCTION_HPU"                    76 sites
    #matrixResult[#tempCounterRows, #tempCounterColumns]  12 sites
    "QuayData".rcu.input.statusByte.%X0                     7 sites
    ENO := TRUE;                                            2 sites

`function` and `type` are two of the lexer's 25 keywords. All 25 are block and
declaration structure — `FUNCTION_BLOCK`, `VAR_INPUT`, `STRUCT`, `REGION` — so
none of them can legitimately appear inside a REGION body, and one that does is
unambiguously a name. That is why this is fixed in the parser and the lexer is
left alone: the lexer feeds `Region.content`, which 27 rules read byte for byte.

`tokenize`, never `tokenize_with_newlines`: production `Region.tokens` carries
no NEWLINE.
"""

from __future__ import annotations

from plc_code.parser.expression_parser import parse_expression, verify_expression_consumed
from plc_code.parser.expressions import BinaryOp, Index, Member, VariableRef
from plc_code.parser.lexer import TokenType, tokenize


def _tokens(source: str):
    return [t for t in tokenize(source) if t.type is not TokenType.EOF]


def _parse(source: str):
    return parse_expression(_tokens(source))


class TestStructuralKeywordAsName:
    def test_a_local_variable_may_be_named_after_a_keyword(self) -> None:
        result = _parse("#function")
        assert result.errors == []
        assert result.expression == VariableRef(line=1, column=1, name="function", is_local=True)

    def test_a_member_may_be_named_after_a_keyword(self) -> None:
        result = _parse('#cpmsSensorParams["SLEWING_AXIS"].type')
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "type"
        assert isinstance(node.base, Index)

    def test_a_local_member_may_be_named_after_a_keyword(self) -> None:
        result = _parse("#state.#type")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "type"
        assert node.is_local is True

    def test_the_whole_keyword_table_is_accepted_as_a_name(self) -> None:
        for keyword in ("var_input", "struct", "region", "rung", "data_block", "end_var"):
            result = _parse(f"#{keyword}")
            assert result.errors == [], keyword
            assert result.expression == VariableRef(line=1, column=1, name=keyword, is_local=True)

    def test_a_keyword_named_variable_works_inside_an_expression(self) -> None:
        result = _parse('#function = "RCU_FUNCTION_HPU"')
        assert result.errors == []
        node = result.expression
        assert isinstance(node, BinaryOp)
        assert node.operator == "="
        assert node.left == VariableRef(line=1, column=1, name="function", is_local=True)

    def test_a_bare_keyword_is_still_not_an_expression(self) -> None:
        # Only a name position accepts a keyword. On its own it stays an error,
        # exactly as a bare identifier does.
        result = _parse("function")
        assert result.errors != []
        assert result.expression is None


class TestMultiDimensionalIndex:
    def test_two_indices_are_both_read(self) -> None:
        result = _parse("#matrixResult[#tempCounterRows, #tempCounterColumns]")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Index)
        assert len(node.indices) == 2
        assert node.indices[0] == VariableRef(line=1, column=15, name="tempCounterRows", is_local=True)

    def test_a_single_index_is_a_list_of_one(self) -> None:
        result = _parse("#arr[#i]")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Index)
        assert node.indices == [VariableRef(line=1, column=6, name="i", is_local=True)]

    def test_three_indices_are_read(self) -> None:
        result = _parse("#cube[#i, #j, #k]")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Index)
        assert len(node.indices) == 3

    def test_an_index_may_be_a_whole_expression(self) -> None:
        result = _parse("#m[#i + 1, #j - 1]")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Index)
        assert all(isinstance(entry, BinaryOp) for entry in node.indices)

    def test_an_empty_index_is_an_error(self) -> None:
        result = _parse("#arr[]")
        assert result.errors != []
        assert result.expression is None

    def test_a_trailing_comma_is_an_error(self) -> None:
        result = _parse("#arr[#i,]")
        assert result.errors != []
        assert result.expression is None

    def test_a_missing_comma_is_an_error(self) -> None:
        result = _parse("#arr[#i #j]")
        assert result.errors != []
        assert result.expression is None


class TestDirectAccess:
    def test_a_bit_selector_is_a_member(self) -> None:
        result = _parse("#statusByte.%X0")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "X0"
        assert node.is_absolute is True

    def test_a_byte_selector_is_read(self) -> None:
        result = _parse("#tempSwapValue.%B1")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "B1"
        assert node.is_absolute is True

    def test_a_bit_selector_ends_a_member_chain(self) -> None:
        result = _parse('"QuayData".rcu.input.statusByte.%X0')
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.is_absolute is True
        assert isinstance(node.base, Member)
        assert node.base.name == "statusByte"
        assert node.base.is_absolute is False

    def test_an_absolute_address_carries_its_numeric_tail(self) -> None:
        result = _parse('"Data".%DBX0.0')
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "0"
        assert node.is_absolute is False
        assert isinstance(node.base, Member)
        assert node.base.name == "DBX0"
        assert node.base.is_absolute is True

    def test_a_numeric_member_needs_no_percent(self) -> None:
        # `#word.0` is bit 0 of `#word`, written without the `%` prefix.
        result = _parse("#word.0")
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "0"
        assert node.is_absolute is False

    def test_a_detached_percent_is_an_error(self) -> None:
        # `%X0` is one lexical unit in SCL; a space breaks it, and the parser
        # applies the same adjacency rule the binary operators use.
        result = _parse("#statusByte.% X0")
        assert result.errors != []
        assert result.expression is None

    def test_a_percent_with_no_selector_is_an_error(self) -> None:
        result = _parse("#statusByte.%")
        assert result.errors != []
        assert result.expression is None


class TestImplicitEnableOutput:
    def test_eno_is_a_variable(self) -> None:
        result = _parse("ENO")
        assert result.errors == []
        assert result.expression == VariableRef(line=1, column=1, name="ENO", is_local=False)

    def test_eno_is_case_insensitive_like_the_rest_of_scl(self) -> None:
        result = _parse("Eno")
        assert result.errors == []
        assert result.expression == VariableRef(line=1, column=1, name="Eno", is_local=False)

    def test_no_other_bare_identifier_is_accepted(self) -> None:
        # The bare-identifier error is what catches everything else the grammar
        # cannot read. Only the one implicit output SCL actually defines is
        # allowed through; widening this would empty the grammar of its ability
        # to refuse.
        result = _parse("ENABLE")
        assert result.errors != []
        assert result.expression is None


class TestQuotedMemberName:
    """TIA Portal quotes a member name that collides with a keyword.

    `#function` and `.type` are one way of writing a name the lexer reserves;
    quoting is the other, and the corpus uses it 80 times:

        "QuayParameters".quayParam.armParams[0].cpmsSensorParams[0]."type" := ...
    """

    def test_a_quoted_member_name_is_read(self) -> None:
        result = _parse('"P".arms[0]."type"')
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "type"
        assert node.is_quoted is True

    def test_an_unquoted_member_is_not_marked_quoted(self) -> None:
        result = _parse('"P".arms[0].type')
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "type"
        assert node.is_quoted is False

    def test_a_quoted_member_chains_like_any_other(self) -> None:
        result = _parse('"P"."type".value')
        assert result.errors == []
        node = result.expression
        assert isinstance(node, Member)
        assert node.name == "value"
        assert isinstance(node.base, Member)
        assert node.base.name == "type"
        assert node.base.is_quoted is True


class TestConsumption:
    def test_every_repaired_shape_consumes_all_its_tokens(self) -> None:
        for source in (
            '#cpmsSensorParams["SLEWING_AXIS"].type',
            "#matrixResult[#tempCounterRows, #tempCounterColumns]",
            '"QuayData".rcu.input.statusByte.%X0',
            "ENO",
        ):
            tokens = _tokens(source)
            result = parse_expression(tokens)
            assert verify_expression_consumed(tokens, result) is True, source
