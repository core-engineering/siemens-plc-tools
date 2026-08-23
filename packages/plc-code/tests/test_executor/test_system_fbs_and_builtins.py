"""System FB instance types and builtins the production sweep found unmapped.

``R_TRIG``/``F_TRIG``/``TONR`` instances, a system type used as a variable type
(``HW_IO``), and the conversions ``SQR``, ``TIME_TO_DINT``, ``TRUNC``,
``SWAP_WORD``, ``BCD16_TO_INT`` -- each a ``NameError`` at class creation or at
the call before. A builtin mapped to a ``lambda`` also rendered without its own
parentheses (``lambda x: x & 0xFF(self.a)``: valid Python, a lambda, never
called) -- every lambda-valued builtin is parenthesized now.
"""

from __future__ import annotations

from pathlib import Path

from plc_code.executor.harness import create_harness
from plc_code.executor.renderer import render
from plc_code.parser.expression_parser import parse_expression
from plc_code.parser.lexer import TokenType, tokenize

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _render(source: str) -> str:
    return render(parse_expression([t for t in tokenize(source) if t.type is not TokenType.EOF]).expression)


def test_a_lambda_builtin_is_called_not_returned() -> None:
    assert _render("INT_TO_USINT(#a)") == "(lambda x: x & 0xFF)(self.a)"
    assert _render("SQR(#a)") == "(lambda x: x * x)(self.a)"
    assert _render("DIS_AIRT()") == "(lambda: 0)()"


def test_edges_retentive_timer_and_conversions_run() -> None:
    harness = create_harness(FIXTURES / "SystemFbs.s7dcl")
    harness.set_inputs(input=False, raw=7, duration=1.5)
    harness.execute()
    assert (harness.get_output("rose"), harness.get_output("fell")) == (False, False)
    harness.set_inputs(input=True)
    harness.execute()
    assert (harness.get_output("rose"), harness.get_output("fell")) == (True, False)
    harness.execute()
    assert harness.get_output("rose") is False
    harness.set_inputs(input=False)
    harness.execute()
    assert harness.get_output("fell") is True
    assert harness.get_output("squared") == 49
    assert harness.get_output("ms") == 1500
    assert harness.get_output("truncated") == 2
    assert harness.get_output("swapped") == 0x3412
    assert harness.get_output("bcd") == 42


def test_the_retentive_timer_accumulates_and_holds() -> None:
    harness = create_harness(FIXTURES / "SystemFbs.s7dcl")
    harness.set_inputs(input=True, raw=0, duration=0.0)
    harness.execute()
    harness.advance_time_ms(60)
    harness.execute()
    assert harness.get_output("held") is False
    harness.set_inputs(input=False)
    harness.advance_time_ms(500)
    harness.execute()  # held, not reset
    harness.set_inputs(input=True)
    harness.advance_time_ms(60)
    harness.execute()
    assert harness.get_output("held") is True
