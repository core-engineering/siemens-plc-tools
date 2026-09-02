"""Standard-access layout: alignment and Bool packing, one rule per test."""

from __future__ import annotations

import pytest

from plc_code.layout.registry import TypeRegistry, UnknownTypeError
from plc_code.layout.rules import layout_fields
from plc_code.parser.models import Block, UserDataType
from plc_code.parser.models import StructField as F
from plc_code.parser.models import VariableDeclaration as V


def _offsets(layout) -> list[tuple[str, int, int, int]]:
    return [(m.path, m.byte_offset, m.bit_offset, m.size_bytes) for m in layout.members if m.is_leaf]


def _registry(*udts: UserDataType) -> TypeRegistry:
    registry = TypeRegistry()
    for udt in udts:
        block = Block(name=udt.name, block_type="TYPE")
        block.user_data_type = udt
        registry.add(block)
    return registry


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


def test_unknown_parent_path_is_reported() -> None:
    with pytest.raises(ValueError, match="x: unknown parent path 'ghost'"):
        layout_fields([V("x", "Int", parent="ghost")], TypeRegistry())


def test_array_of_int_is_contiguous() -> None:
    layout = layout_fields([V("a", "Array[0..3] of Int"), V("b", "Byte")], TypeRegistry())
    assert _offsets(layout) == [
        ("a[0]", 0, 0, 2),
        ("a[1]", 2, 0, 2),
        ("a[2]", 4, 0, 2),
        ("a[3]", 6, 0, 2),
        ("b", 8, 0, 1),
    ]
    whole = next(m for m in layout.members if m.path == "a")
    assert (whole.byte_offset, whole.size_bytes, whole.is_leaf) == (0, 8, False)


def test_array_of_bool_packs_then_pads_to_even() -> None:
    layout = layout_fields([V("a", "Array[0..9] of Bool"), V("b", "Byte")], TypeRegistry())
    rows = _offsets(layout)
    assert rows[0] == ("a[0]", 0, 0, 0) and rows[8] == ("a[8]", 1, 0, 0) and rows[9] == ("a[9]", 1, 1, 0)
    assert rows[10] == ("b", 2, 0, 1)


def test_array_of_byte_with_odd_count_pads_to_even() -> None:
    layout = layout_fields([V("a", "Array[0..2] of Byte"), V("b", "Byte")], TypeRegistry())
    assert _offsets(layout)[-1] == ("b", 4, 0, 1)


def test_array_after_bool_starts_on_even_byte() -> None:
    layout = layout_fields([V("x", "Bool"), V("a", "Array[0..1] of Byte")], TypeRegistry())
    assert _offsets(layout)[1] == ("a[0]", 2, 0, 1)


def test_two_dimensional_array_is_row_major() -> None:
    layout = layout_fields([V("a", "Array[1..2, 0..1] of Int")], TypeRegistry())
    assert [m.path for m in layout.members if m.is_leaf] == ["a[1,0]", "a[1,1]", "a[2,0]", "a[2,1]"]


def test_inline_struct_is_even_aligned_and_padded() -> None:
    fields = [
        V("c", "Byte"),
        V("s", "Struct"),
        V("x", "Bool", parent="s"),
        V("y", "Byte", parent="s"),
        V("z", "Byte"),
    ]
    layout = layout_fields(fields, TypeRegistry())
    assert _offsets(layout) == [("c", 0, 0, 1), ("s.x", 2, 0, 0), ("s.y", 3, 0, 1), ("z", 4, 0, 1)]
    struct = next(m for m in layout.members if m.path == "s")
    assert (struct.byte_offset, struct.size_bytes) == (2, 2)


def test_nested_struct_paths() -> None:
    fields = [
        V("s", "Struct"),
        V("inner", "Struct", parent="s"),
        V("y", "DInt", parent="s.inner"),
        V("z", "Real", parent="s"),
    ]
    layout = layout_fields(fields, TypeRegistry())
    assert _offsets(layout) == [("s.inner.y", 0, 0, 4), ("s.z", 4, 0, 4)]


def test_udt_member_uses_registry_and_pads() -> None:
    motor = UserDataType(name="typeMotor", fields=[F("speed", "Real"), F("running", "Bool")])
    layout = layout_fields([V("m", "_.typeMotor"), V("i", "Int")], _registry(motor))
    assert _offsets(layout) == [("m.speed", 0, 0, 4), ("m.running", 4, 0, 0), ("i", 6, 0, 2)]


def test_udt_in_udt_and_array_of_udt() -> None:
    motor = UserDataType(name="typeMotor", fields=[F("speed", "Real"), F("running", "Bool")])
    axis = UserDataType(name="typeAxis", fields=[F("motor", "_.typeMotor"), F("limit", "Int")])
    layout = layout_fields([V("axes", "Array[1..2] of _.typeAxis")], _registry(motor, axis))
    assert _offsets(layout) == [
        ("axes[1].motor.speed", 0, 0, 4),
        ("axes[1].motor.running", 4, 0, 0),
        ("axes[1].limit", 6, 0, 2),
        ("axes[2].motor.speed", 8, 0, 4),
        ("axes[2].motor.running", 12, 0, 0),
        ("axes[2].limit", 14, 0, 2),
    ]
    assert layout.total_size == 16


def test_udt_with_nested_inline_struct_fields() -> None:
    fields = [F("a", "Int"), F("s", "Struct"), F("x", "Bool", parent="s")]
    probe = UserDataType(name="typeProbe", fields=fields)
    layout = layout_fields([V("p", "_.typeProbe")], _registry(probe))
    assert _offsets(layout) == [("p.a", 0, 0, 2), ("p.s.x", 2, 0, 0)]


def test_array_of_inline_struct_uses_the_element_members() -> None:
    fields = [
        V("arr", "Array[0..1] of Struct"),
        V("x", "Bool", parent="arr"),
        V("y", "Int", parent="arr"),
    ]
    layout = layout_fields(fields, TypeRegistry())
    assert _offsets(layout) == [
        ("arr[0].x", 0, 0, 0),
        ("arr[0].y", 2, 0, 2),
        ("arr[1].x", 4, 0, 0),
        ("arr[1].y", 6, 0, 2),
    ]
    assert layout.total_size == 8


def test_array_of_string_keeps_the_declared_length() -> None:
    layout = layout_fields([V("s", "Array[0..1] of String[4]")], TypeRegistry())
    assert _offsets(layout) == [("s[0]", 0, 0, 6), ("s[1]", 6, 0, 6)]
    assert layout.total_size == 12


def test_unknown_udt_raises() -> None:
    with pytest.raises(UnknownTypeError, match="typeGhost"):
        layout_fields([V("g", "_.typeGhost")], TypeRegistry())
