"""Positional arguments to a named block are bound by the callee's declared signature.

SCL lets a FUNCTION be called with positional arguments — `"Scaling"(#raw, 2.0)` —
where the position decides which declared parameter receives the value. The old
text translator, and the AST renderer that replaced it byte for byte, both
DROPPED every unnamed argument: the generated Python called the block with an
empty input dict, the block computed on defaults, and nothing reported it. Five
production projects hold 97 such calls in 3 blocks, every one of them running on
no inputs.

A transpiler sees one block at a time, but the project holds every source, and the
runtime already resolves a block by name to read its kind. The same resolution now
reads its declared inputs, in order, and a positional argument is bound to the
next one. Where no signature can be resolved — the block is outside the project,
the call passes more arguments than the signature has parameters, or a positional
argument would bind a name that a named argument in the same call already uses —
the transpile fails loudly. Without a signature the right binding is a guess, and
this codebase does not guess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plc_code.executor.arguments import (
    PositionalBindingError,
    positional_parameter_names,
)
from plc_code.executor.generator import generate_statements
from plc_code.executor.harness import create_harness
from plc_code.executor.renderer import UnsupportedExpression, render
from plc_code.executor.runtime import PLCRuntime
from plc_code.parser.expression_parser import parse_expression
from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.statement_parser import parse_statements

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _resolver(signatures: dict[str, list[str]]):
    return lambda name: signatures.get(name)


def _expr(source: str):
    tokens = [t for t in tokenize(source) if t.type is not TokenType.EOF]
    result = parse_expression(tokens)
    assert result.errors == [], result.errors
    return result.expression


def _statements(source: str):
    tokens = [t for t in tokenize(source) if t.type is not TokenType.EOF]
    result = parse_statements(tokens)
    assert result.errors == [], result.errors
    return result.statements


class TestTheBinder:
    def test_positional_arguments_take_the_first_declared_inputs_in_order(self) -> None:
        names = positional_parameter_names(
            "Scaling",
            positional_count=2,
            already_named=set(),
            resolver=_resolver({"Scaling": ["input", "gain"]}),
        )
        assert names == ["input", "gain"]

    def test_a_block_with_no_resolvable_signature_is_an_error(self) -> None:
        with pytest.raises(PositionalBindingError, match="Scaling"):
            positional_parameter_names(
                "Scaling", positional_count=1, already_named=set(), resolver=_resolver({})
            )

    def test_no_resolver_at_all_is_an_error(self) -> None:
        with pytest.raises(PositionalBindingError):
            positional_parameter_names("Scaling", positional_count=1, already_named=set(), resolver=None)

    def test_more_arguments_than_parameters_is_an_error(self) -> None:
        with pytest.raises(PositionalBindingError, match="2 positional"):
            positional_parameter_names(
                "Scaling", positional_count=2, already_named=set(), resolver=_resolver({"Scaling": ["input"]})
            )

    def test_a_positional_argument_may_not_shadow_a_named_one(self) -> None:
        with pytest.raises(PositionalBindingError, match="input"):
            positional_parameter_names(
                "Scaling",
                positional_count=1,
                already_named={"input"},
                resolver=_resolver({"Scaling": ["input"]}),
            )

    def test_the_shadow_check_ignores_case_like_scl_does(self) -> None:
        with pytest.raises(PositionalBindingError, match="input"):
            positional_parameter_names(
                "Scaling",
                positional_count=1,
                already_named={"INPUT"},
                resolver=_resolver({"Scaling": ["input"]}),
            )

    def test_zero_positional_arguments_need_no_resolver(self) -> None:
        assert (
            positional_parameter_names("Scaling", positional_count=0, already_named=set(), resolver=None)
            == []
        )


class TestTheRendererSite:
    def test_a_positional_argument_in_expression_position_is_named_from_the_signature(self) -> None:
        node = _expr('"Scaling"(#raw, 2.0)')
        rendered = render(node, signature_resolver=_resolver({"Scaling": ["input", "gain"]}))
        assert '"input": self.raw' in rendered
        assert '"gain": 2.0' in rendered

    def test_positional_then_named_binds_in_declaration_order(self) -> None:
        node = _expr('"Scaling"(#raw, gain := 2.0)')
        rendered = render(node, signature_resolver=_resolver({"Scaling": ["input", "gain"]}))
        assert '"input": self.raw' in rendered
        assert '"gain": 2.0' in rendered

    def test_without_a_signature_the_render_raises_instead_of_dropping(self) -> None:
        node = _expr('"Scaling"(#raw)')
        with pytest.raises(UnsupportedExpression, match="Scaling"):
            render(node)

    def test_a_builtin_keeps_its_positional_form(self) -> None:
        # Builtins are not blocks; positional IS their correct form and needs no signature.
        assert render(_expr("ABS(#x)")) == "abs(self.x)"


class TestTheGeneratorSites:
    def test_a_positional_call_statement_is_bound_and_written_back(self) -> None:
        lines = generate_statements(
            _statements('"Doubler"(#value, result := #tmp);'),
            signature_resolver=_resolver({"Doubler": ["x"]}),
        )
        joined = "\n".join(lines)
        assert '"x": self.value' in joined
        assert '"result": self.tmp' in joined

    def test_a_positional_call_statement_without_a_signature_raises(self) -> None:
        from plc_code.executor.generator import UnsupportedStatement

        with pytest.raises(UnsupportedStatement, match="Doubler"):
            generate_statements(_statements('"Doubler"(#value);'))

    def test_a_positional_assignment_rhs_is_bound(self) -> None:
        lines = generate_statements(
            _statements('#ret := "RetWithOut"(#value, dbl => #d);'),
            signature_resolver=_resolver({"RetWithOut": ["x"]}),
        )
        joined = "\n".join(lines)
        assert '"x": self.value' in joined
        assert "self.d = " in joined

    def test_an_fb_instance_call_with_a_positional_argument_raises(self) -> None:
        # An instance call needs a second lookup (instance -> declared type) the
        # generator does not hold; it raises rather than guess. Zero corpus sites.
        from plc_code.executor.generator import UnsupportedStatement

        with pytest.raises(UnsupportedStatement, match="positional"):
            generate_statements(
                _statements("#timer(#input, #delay);"), signature_resolver=_resolver({"TON": ["IN", "PT"]})
            )


class TestEndToEnd:
    def test_positional_calls_execute_with_the_right_inputs(self) -> None:
        harness = create_harness(FIXTURES / "CallsPositional.s7dcl")
        harness.set_inputs(value=5.0)
        harness.execute()
        assert harness.get_output("ret") == 6.0  # RetWithOut returns x + 1
        assert harness.get_output("doubled") == 10.0
        assert harness.get_output("tripled") == 15.0
        assert harness.get_output("viaStatement") == 10.0  # Doubler's result written back


class TestTheRuntimeResolver:
    def test_a_block_with_outputs_offers_its_inputs_only(self) -> None:
        # RetWithOut declares one input and two outputs: only the input is offered, so
        # a call reaching past it is refused by the binder instead of guessed at.
        runtime = PLCRuntime(block_search_paths=[FIXTURES])
        assert runtime.block_signature("RetWithOut") == ["x"]
        assert runtime.block_signature("NoSuchBlock") is None

    def test_a_block_without_outputs_offers_its_in_outs_after_its_inputs(self, tmp_path: Path) -> None:
        (tmp_path / "Swap.s7dcl").write_text(
            'FUNCTION "Swap" : Void\n'
            "    VAR_INPUT\n        gain : Real;\n    END_VAR\n"
            "    VAR_IN_OUT\n        a : Real;\n        b : Real;\n    END_VAR\n"
            "BEGIN\n    #a := #b * #gain;\nEND_FUNCTION\n"
        )
        assert PLCRuntime(block_search_paths=[tmp_path]).block_signature("Swap") == ["gain", "a", "b"]

    def test_a_callee_is_found_anywhere_below_a_search_path(self, tmp_path: Path) -> None:
        nested = tmp_path / "lib" / "deep"
        nested.mkdir(parents=True)
        (nested / "Doubler.s7dcl").write_text((FIXTURES / "Doubler.s7dcl").read_text())
        assert PLCRuntime(block_search_paths=[tmp_path]).block_signature("Doubler") == ["x"]
