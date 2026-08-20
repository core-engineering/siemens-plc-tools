"""Named argument bindings in calls that appear inside an expression.

SCL binds a call's arguments by name far more often than by position, and the
corpus writes both directions:

    "ScalingAnalogicInput"(input := "QuayData".arms[#armNumber].input.pressure)
    RD_SYS_T(OUT => #localTime)

The parameter name is a bare identifier, which is not a valid expression on its
own, so the grammar rejected the argument before it ever reached the `:=`. That
accounted for roughly 166 of the 263 expression errors measured across five
production projects.

Shapes are transcribed from the corpus, not invented. `tokenize`, never
`tokenize_with_newlines`: production `Region.tokens` carries no NEWLINE.
"""

from __future__ import annotations

import dataclasses

import pytest

from plc_code.parser.expression_parser import parse_expression, verify_expression_consumed
from plc_code.parser.expressions import (
    BinaryOp,
    CallArgument,
    FunctionCall,
    Index,
    Literal,
    Member,
    VariableRef,
)
from plc_code.parser.lexer import TokenType, tokenize


def _tokens(source: str):
    return [t for t in tokenize(source) if t.type is not TokenType.EOF]


def _parse(source: str):
    return parse_expression(_tokens(source))


class TestCallArgumentModel:
    def test_a_bare_argument_carries_no_name_and_no_direction(self) -> None:
        argument = CallArgument(value=Literal(line=1, column=1, value="1"))
        assert argument.name == ""
        assert argument.is_output is False

    def test_the_node_is_frozen(self) -> None:
        argument = CallArgument(value=Literal(line=1, column=1, value="1"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            argument.name = "IN"  # type: ignore[misc]

    def test_two_arguments_with_the_same_content_are_equal(self) -> None:
        first = CallArgument(value=Literal(line=1, column=1, value="1"), name="IN")
        second = CallArgument(value=Literal(line=1, column=1, value="1"), name="IN")
        assert first == second


class TestInputBinding:
    def test_a_named_input_carries_its_name(self) -> None:
        result = _parse('"PolyEval"(x := #ll)')
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert len(call.arguments) == 1
        argument = call.arguments[0]
        assert argument.name == "x"
        assert argument.is_output is False
        assert argument.value == VariableRef(line=1, column=17, name="ll", is_local=True)

    def test_every_binding_of_a_multi_argument_call_is_read(self) -> None:
        result = _parse('"PolyEval"(p := #p, n := #n, x := #ll)')
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert [argument.name for argument in call.arguments] == ["p", "n", "x"]
        assert all(argument.is_output is False for argument in call.arguments)

    def test_a_bound_value_may_be_a_whole_expression(self) -> None:
        result = _parse('"ScalingAnalogicInput"(input := "QuayData".arms[#armNumber].input.pressure)')
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        value = call.arguments[0].value
        assert isinstance(value, Member)
        assert value.name == "pressure"
        assert isinstance(value.base, Member)
        assert isinstance(value.base.base, Index)

    def test_a_bound_value_may_be_another_call(self) -> None:
        result = _parse('"CheckVelProfile"(profile := "MakeProfile"(v := #v0))')
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        inner = call.arguments[0].value
        assert isinstance(inner, FunctionCall)
        assert inner.name == "MakeProfile"
        assert inner.arguments[0].name == "v"

    def test_a_builtin_takes_named_arguments_too(self) -> None:
        result = _parse("SCALE_X(MIN := #lo, VALUE := #v, MAX := #hi)")
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert call.is_quoted is False
        assert [argument.name for argument in call.arguments] == ["MIN", "VALUE", "MAX"]


class TestOutputBinding:
    def test_an_output_arrow_marks_the_argument(self) -> None:
        result = _parse("RD_SYS_T(OUT => #localTime)")
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        argument = call.arguments[0]
        assert argument.name == "OUT"
        assert argument.is_output is True
        assert argument.value == VariableRef(line=1, column=17, name="localTime", is_local=True)

    def test_input_and_output_bindings_mix_in_source_order(self) -> None:
        result = _parse('"Convert"(IN := #raw, OUT => #scaled)')
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert [(a.name, a.is_output) for a in call.arguments] == [("IN", False), ("OUT", True)]

    def test_a_split_arrow_is_not_an_output_binding(self) -> None:
        # `=` and `>` separated by a space are two operators, not `=>`. The
        # adjacency rule is the same one the binary operators use.
        result = _parse("RD_SYS_T(OUT = > #localTime)")
        assert result.errors != []
        assert result.expression is None


class TestPositionalArgumentsStillWork:
    def test_a_positional_argument_carries_an_empty_name(self) -> None:
        result = _parse("ABS(#x)")
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert call.arguments == [CallArgument(value=VariableRef(line=1, column=5, name="x", is_local=True))]

    def test_positional_and_named_arguments_mix(self) -> None:
        result = _parse('"Limit"(#value, MAX := #ceiling)')
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert [(a.name, a.is_output) for a in call.arguments] == [("", False), ("MAX", False)]

    def test_a_comparison_argument_is_still_positional(self) -> None:
        result = _parse("ABS(#x > #y)")
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert call.arguments[0].name == ""
        assert isinstance(call.arguments[0].value, BinaryOp)

    def test_a_call_with_no_arguments_is_unchanged(self) -> None:
        result = _parse('"Reset"()')
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert call.arguments == []


class TestMalformedBindings:
    def test_a_missing_value_after_the_assignment_is_an_error(self) -> None:
        result = _parse('"PolyEval"(x := )')
        assert result.errors != []
        assert result.expression is None

    def test_a_missing_value_after_the_arrow_is_an_error(self) -> None:
        result = _parse("RD_SYS_T(OUT => )")
        assert result.errors != []
        assert result.expression is None

    def test_the_whole_call_fails_when_one_binding_fails(self) -> None:
        result = _parse('"PolyEval"(p := #p, n := , x := #ll)')
        assert result.errors != []
        assert result.expression is None


class TestConsumption:
    def test_a_named_call_consumes_all_its_tokens(self) -> None:
        tokens = _tokens('"PolyEval"(p := #p, n := #n, x := #ll)')
        result = parse_expression(tokens)
        assert verify_expression_consumed(tokens, result) is True


class TestQuotedParameterName:
    """A parameter name may be quoted, which an earlier revision denied.

    That revision asserted `"x" := #A` was an error, on the belief that SCL
    parameter names are always bare identifiers. The corpus disproves it — TIA
    Portal quotes a parameter name and leaves its neighbour bare in the same
    call:

        #phase := "Atan2"("x" := #A, y := #B);
    """

    def test_a_quoted_parameter_name_is_a_binding(self) -> None:
        result = _parse('"Atan2"("x" := #A, y := #B)')
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert [(a.name, a.is_quoted_name) for a in call.arguments] == [("x", True), ("y", False)]

    def test_a_quoted_output_binding_is_read(self) -> None:
        result = _parse('"Convert"("OUT" => #scaled)')
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        argument = call.arguments[0]
        assert argument.name == "OUT"
        assert argument.is_quoted_name is True
        assert argument.is_output is True

    def test_a_quoted_name_with_no_binding_is_still_a_variable(self) -> None:
        # Without `:=` or `=>` the quoted name is an ordinary global read, which
        # is what makes the lookahead necessary rather than optional.
        result = _parse('"Limit"("Ceiling")')
        assert result.errors == []
        call = result.expression
        assert isinstance(call, FunctionCall)
        assert call.arguments[0].name == ""
        assert call.arguments[0].value == VariableRef(line=1, column=9, name="Ceiling", is_local=False)
