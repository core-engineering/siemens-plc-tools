"""S7 elementary type sizes (standard access)."""

from __future__ import annotations

import pytest

from plc_code.layout.sizes import elementary_size


@pytest.mark.parametrize(
    ("name", "bits"),
    [
        ("Bool", 1), ("Byte", 8), ("Char", 8), ("SInt", 8), ("USInt", 8),
        ("Int", 16), ("UInt", 16), ("Word", 16), ("Date", 16), ("WChar", 16),
        ("DInt", 32), ("UDInt", 32), ("DWord", 32), ("Real", 32), ("Time", 32),
        ("Time_Of_Day", 32), ("TOD", 32),
        ("LInt", 64), ("ULInt", 64), ("LWord", 64), ("LReal", 64), ("LTime", 64),
        ("LTOD", 64), ("LDT", 64), ("Date_And_Time", 64), ("DT", 64),
        ("DTL", 96),
    ],
)
def test_sizes(name: str, bits: int) -> None:
    size = elementary_size(name)
    assert size is not None and size.bits == bits


def test_names_are_case_insensitive() -> None:
    assert elementary_size("lreal") == elementary_size("LReal")


def test_udt_and_struct_are_not_elementary() -> None:
    assert elementary_size("typeMotor") is None
    assert elementary_size("Struct") is None
