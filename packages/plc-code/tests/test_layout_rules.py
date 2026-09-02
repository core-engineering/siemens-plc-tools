"""Standard-access layout: alignment and Bool packing, one rule per test."""

from __future__ import annotations

from plc_code.layout.registry import TypeRegistry
from plc_code.layout.rules import layout_fields
from plc_code.parser.models import VariableDeclaration as V


def _offsets(layout) -> list[tuple[str, int, int, int]]:
    return [(m.path, m.byte_offset, m.bit_offset, m.size_bytes) for m in layout.members if m.is_leaf]


def test_two_byte_members_are_word_aligned() -> None:
    layout = layout_fields([V("a", "Byte"), V("b", "Int"), V("c", "Byte"), V("d", "DInt")], TypeRegistry())
    assert _offsets(layout) == [("a", 0, 0, 1), ("b", 2, 0, 2), ("c", 4, 0, 1), ("d", 6, 0, 4)]
    assert layout.total_size == 10


def test_bools_pack_bit_by_bit() -> None:
    layout = layout_fields([V(f"b{i}", "Bool") for i in range(9)] + [V("x", "Byte")], TypeRegistry())
    rows = _offsets(layout)
    assert rows[0] == ("b0", 0, 0, 0) and rows[7] == ("b7", 0, 7, 0) and rows[8] == ("b8", 1, 0, 0)
    assert rows[9] == ("x", 2, 0, 1)


def test_bool_then_int_skips_to_next_even_byte() -> None:
    layout = layout_fields([V("b", "Bool"), V("i", "Int")], TypeRegistry())
    assert _offsets(layout) == [("b", 0, 0, 0), ("i", 2, 0, 2)]


def test_bool_then_byte_takes_next_byte() -> None:
    layout = layout_fields([V("b", "Bool"), V("c", "Byte")], TypeRegistry())
    assert _offsets(layout) == [("b", 0, 0, 0), ("c", 1, 0, 1)]


def test_string_is_word_aligned_and_n_plus_2() -> None:
    fields = [V("c", "Byte"), V("s", "String[5]"), V("w", "WString[3]"), V("i", "Int")]
    layout = layout_fields(fields, TypeRegistry())
    assert _offsets(layout) == [("c", 0, 0, 1), ("s", 2, 0, 7), ("w", 10, 0, 10), ("i", 20, 0, 2)]


def test_eight_byte_types_align_to_even_not_eight() -> None:
    layout = layout_fields([V("i", "Int"), V("l", "LReal")], TypeRegistry())
    assert _offsets(layout) == [("i", 0, 0, 2), ("l", 2, 0, 8)]


def test_total_size_rounds_up_to_even() -> None:
    layout = layout_fields([V("a", "Byte"), V("b", "Byte"), V("c", "Byte")], TypeRegistry())
    assert layout.total_size == 4


def test_empty_layout() -> None:
    layout = layout_fields([], TypeRegistry())
    assert layout.total_size == 0 and layout.members == []


def test_size_bits_reported_for_bool() -> None:
    layout = layout_fields([V("b", "Bool")], TypeRegistry())
    member = layout.leaf("b")
    assert (member.size_bits, member.size_bytes) == (1, 0)


def test_dtl_is_twelve_bytes() -> None:
    layout = layout_fields([V("t", "DTL"), V("i", "Int")], TypeRegistry())
    assert _offsets(layout) == [("t", 0, 0, 12), ("i", 12, 0, 2)]
