"""``value.%Xn`` / ``%Bn`` / ``%Wn``: reading and writing a slice of an integer.

Five production blocks use it; the renderer refused it (before that, it emitted
`self.word.%X0`, Python that does not parse). A read is `_bit_slice(value, width,
index)`; a write rewrites the slice inside the base, which is the lvalue.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plc_code.executor.harness import create_harness
from plc_code.executor.renderer import UnsupportedExpression, render
from plc_code.executor.runtime import _bit_slice, _with_bit_slice
from plc_code.parser.expression_parser import parse_expression
from plc_code.parser.lexer import TokenType, tokenize

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_the_helpers() -> None:
    assert _bit_slice(0b1010, 1, 1) is True and _bit_slice(0b1010, 1, 0) is False
    assert _bit_slice(0xA5F0, 8, 0) == 0xF0 and _bit_slice(0xA5F0, 8, 1) == 0xA5
    assert _with_bit_slice(0xA5F0, 1, 0, True) == 0xA5F1
    assert _with_bit_slice(0xA5F0, 8, 1, 0x12) == 0x12F0


def test_reads_and_writes_run_on_the_harness() -> None:
    harness = create_harness(FIXTURES / "BitSlices.s7dcl")
    harness.set_inputs(status=0x81, on=True)
    harness.execute()
    assert harness.get_output("bit0") is True and harness.get_output("bit7") is True
    assert harness.get_output("packed") == 0x25F1  # bit 0 set, bit 15 cleared
    assert harness.get_output("lowByte") == 0xF1


def test_absolute_addressing_is_still_refused_with_its_line() -> None:
    tree = parse_expression([t for t in tokenize("%DB5.%DBX31.1") if t.type is not TokenType.EOF]).expression
    assert tree is not None
    with pytest.raises(UnsupportedExpression, match="absolute"):
        render(tree)
