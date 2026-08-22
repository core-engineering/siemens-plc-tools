"""Unit tests for `render` over `FunctionCall` (Task 5).

Every expected value was verified against the (now-deleted) text translator while
this renderer was being proven equivalent to it (see the task report), not copied
from the brief's table -- the two `sqrt`/`atan2` probes there and here matched what
the text translator actually did. The quoted-name-parameter case pins a
pre-existing `_build_named_call` bug (`""x"": ...`, not valid Python) that this
renderer reproduces on purpose, because it gets there by calling
`_build_named_call` itself rather than guessing at its behaviour -- see
`renderer._render_named_call`'s docstring.
"""

from __future__ import annotations

import pytest

from plc_code.executor.renderer import UnsupportedExpression, render
from plc_code.parser.expressions import CallArgument, FunctionCall, Literal, VariableRef


def _local(name: str) -> VariableRef:
    return VariableRef(line=1, column=1, name=name, is_local=True)


def test_a_mapped_builtin_renders_through_the_builtin_map() -> None:
    call = FunctionCall(line=1, column=1, name="ABS", arguments=[CallArgument(value=_local("x"))])
    assert render(call) == "abs(self.x)"


def test_sqrt_maps_to_the_math_module() -> None:
    call = FunctionCall(line=1, column=1, name="SQRT", arguments=[CallArgument(value=_local("x"))])
    assert render(call) == "math.sqrt(self.x)"


def test_atan2_takes_two_positional_arguments() -> None:
    call = FunctionCall(
        line=1,
        column=1,
        name="ATAN2",
        arguments=[CallArgument(value=_local("y")), CallArgument(value=_local("x"))],
    )
    assert render(call) == "math.atan2(self.y, self.x)"


def test_int_to_real_maps_to_float() -> None:
    call = FunctionCall(line=1, column=1, name="INT_TO_REAL", arguments=[CallArgument(value=_local("n"))])
    assert render(call) == "float(self.n)"


def test_an_unmapped_builtin_keeps_its_bare_spelling() -> None:
    call = FunctionCall(line=1, column=1, name="UNKNOWNFN", arguments=[CallArgument(value=_local("x"))])
    assert render(call) == "UNKNOWNFN(self.x)"


def test_lower_bound_with_the_arr_dim_shape_becomes_a_lambda_call() -> None:
    call = FunctionCall(
        line=1,
        column=1,
        name="LOWER_BOUND",
        arguments=[
            CallArgument(value=_local("a"), name="ARR"),
            CallArgument(value=Literal(line=1, column=1, value="1"), name="DIM"),
        ],
    )
    assert render(call) == "(lambda arr, dim: 0)(self.a, 1)"


def test_a_quoted_call_with_one_named_argument() -> None:
    call = FunctionCall(
        line=1,
        column=1,
        name="Scaling",
        is_quoted=True,
        arguments=[CallArgument(value=_local("x"), name="input")],
    )
    assert render(call) == 'self._runtime.call_named_block("Scaling", {"input": self.x}, {})["Scaling"]'


def test_a_quoted_call_with_two_named_arguments() -> None:
    call = FunctionCall(
        line=1,
        column=1,
        name="Atan2",
        is_quoted=True,
        arguments=[
            CallArgument(value=_local("a"), name="y"),
            CallArgument(value=_local("b"), name="x"),
        ],
    )
    expected = 'self._runtime.call_named_block("Atan2", {"y": self.a, "x": self.b}, {})["Atan2"]'
    assert render(call) == expected


def test_a_quoted_call_with_a_positional_argument_drops_it() -> None:
    call = FunctionCall(
        line=1,
        column=1,
        name="Block",
        is_quoted=True,
        arguments=[CallArgument(value=_local("a"))],
    )
    assert render(call) == 'self._runtime.call_named_block("Block", {}, {})["Block"]'


def test_a_quoted_parameter_name_reproduces_the_old_text_translators_double_quote_bug() -> None:
    """Pinned because it comes from calling `_build_named_call`, not from reasoning
    about what it should do -- see `renderer._render_named_call`'s docstring."""
    call = FunctionCall(
        line=1,
        column=1,
        name="Block",
        is_quoted=True,
        arguments=[CallArgument(value=_local("a"), name="x", is_quoted_name=True)],
    )
    assert render(call) == 'self._runtime.call_named_block("Block", {""x"": self.a}, {})["Block"]'


def test_a_bare_builtin_call_with_an_output_argument_raises() -> None:
    """A bare call has nowhere to route `=>` -- see `_render_builtin_call`'s
    docstring. The message must name both the builtin and the bound parameter, so a
    reader of the traceback knows which call and which argument to fix."""
    call = FunctionCall(
        line=1,
        column=1,
        name="RD_SYS_T",
        arguments=[CallArgument(value=_local("localTime"), name="OUT", is_output=True)],
    )
    with pytest.raises(UnsupportedExpression) as exc_info:
        render(call)
    message = str(exc_info.value)
    assert "RD_SYS_T" in message
    assert "OUT" in message


def test_a_bare_builtin_call_with_only_named_input_arguments_still_renders_positionally() -> None:
    """`:=` bindings are unaffected by the output-binding raise above -- their names
    are still discarded and their values still rendered positionally, exactly as
    before this fix. `ATAN2` maps to `math.atan2` in `BUILTIN_MAP`, so the expected
    value is the positional-equivalent shape's rendering (verified directly against
    the old text path while this renderer was being proven equivalent to it): the
    old path does not honour `:=` naming for a bare call at all (it rewrites `:=`
    to `==` via `OPERATOR_MAP`), so the positional shape was the only one where the
    old path's output meant what `render` also means."""
    expected = "math.atan2(self.a, self.b)"
    call = FunctionCall(
        line=1,
        column=1,
        name="ATAN2",
        arguments=[
            CallArgument(value=_local("a"), name="y"),
            CallArgument(value=_local("b"), name="x"),
        ],
    )
    assert render(call) == expected


def test_an_output_bound_argument_is_dropped_from_the_inputs_dict() -> None:
    call = FunctionCall(
        line=1,
        column=1,
        name="Block",
        is_quoted=True,
        arguments=[CallArgument(value=_local("out"), name="y", is_output=True)],
    )
    assert render(call) == 'self._runtime.call_named_block("Block", {}, {})["Block"]'
