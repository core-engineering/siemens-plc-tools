"""Tests for quoted-name sub-block invocation: "BlockName"(...) syntax.

SCL allows calling other FUNCTION or FUNCTION_BLOCK blocks using their
quoted name:  "BlockName"(param1 := val1, output1 => var1).
The executor must discover the sub-block file, compile it, and execute it
inline, wiring inputs/outputs as specified by the call parameters.
"""

from pathlib import Path

import pytest

from plc_code.executor.harness import create_harness

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestNamedBlockCall:
    """Tests for 'BlockName'(...) call syntax."""

    def test_simple_sub_block_call(self) -> None:
        """CallsDoubler calls Doubler twice: value -> doubled -> quadrupled."""
        harness = create_harness(FIXTURES_DIR / "CallsDoubler.s7dcl")
        harness.set_inputs(value=3.0)
        harness.execute()
        out = harness.get_outputs()
        # Doubler(3.0) = 6.0 (intermediate / doubled)
        assert out["doubled"] == pytest.approx(6.0)
        # Doubler(6.0) = 12.0 (quadrupled)
        assert out["quadrupled"] == pytest.approx(12.0)

    def test_sub_block_call_with_zero(self) -> None:
        """Edge case: zero input."""
        harness = create_harness(FIXTURES_DIR / "CallsDoubler.s7dcl")
        harness.set_inputs(value=0.0)
        harness.execute()
        out = harness.get_outputs()
        assert out["doubled"] == pytest.approx(0.0)
        assert out["quadrupled"] == pytest.approx(0.0)

    def test_sub_block_call_with_negative(self) -> None:
        """Edge case: negative input."""
        harness = create_harness(FIXTURES_DIR / "CallsDoubler.s7dcl")
        harness.set_inputs(value=-5.0)
        harness.execute()
        out = harness.get_outputs()
        assert out["doubled"] == pytest.approx(-10.0)
        assert out["quadrupled"] == pytest.approx(-20.0)

    def test_return_value_consumed_with_output_params(self) -> None:
        """A FUNCTION whose return value is consumed in an assignment AND which
        also binds `=>` VAR_OUTPUT params: BOTH must be captured.

        Regression: the expression path used for the return value dropped the
        `=>` output bindings, leaving the targets at their default (0.0).
        """
        harness = create_harness(FIXTURES_DIR / "CallsRetWithOut.s7dcl")
        harness.set_inputs(value=4.0)
        harness.execute()
        out = harness.get_outputs()
        assert out["ret"] == pytest.approx(5.0)  # return value x + 1
        assert out["doubled"] == pytest.approx(8.0)  # => output x * 2
        assert out["tripled"] == pytest.approx(12.0)  # => output x * 3
